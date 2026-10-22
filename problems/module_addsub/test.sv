`timescale 1 ps/1 ps
`define OK 12
`define INCORRECT 13


module stimulus_gen (
	input clk,
	output logic [31:0] a,
	output logic [31:0] b,
	output logic sub
);

	initial begin
		@(posedge clk) begin a <= 32'd5; b <= 32'd3; sub <= 1'd0; end
		@(posedge clk) begin a <= 32'd5; b <= 32'd3; sub <= 1'd1; end
		@(posedge clk) begin a <= 32'd0; b <= 32'd0; sub <= 1'd0; end
		@(posedge clk) begin a <= 32'd0; b <= 32'd0; sub <= 1'd1; end
		@(posedge clk) begin a <= 32'd4294967295; b <= 32'd1; sub <= 1'd0; end
		@(posedge clk) begin a <= 32'd4294967295; b <= 32'd1; sub <= 1'd1; end
		@(posedge clk) begin a <= 32'd2147483648; b <= 32'd2147483648; sub <= 1'd0; end
		@(posedge clk) begin a <= 32'd2147483648; b <= 32'd2147483648; sub <= 1'd1; end
		repeat(300) @(posedge clk, negedge clk) begin a <= $random; b <= $random; sub <= $random; end
		#1 $finish;
	end

endmodule

module tb();

	typedef struct packed {
		int errors;
		int errortime;
		int errors_sum;
		int errortime_sum;

		int clocks;
	} stats;

	stats stats1;

	reg clk=0;
	initial forever
		#5 clk = ~clk;

	logic [31:0] a;
	logic [31:0] b;
	logic sub;
	logic [31:0] sum_ref;
	logic [31:0] sum_dut;

	initial begin
		$dumpfile("wave.vcd");
		$dumpvars(1, stim1.clk, tb_mismatch, a, b, sub, sum_ref, sum_dut);
	end

	wire tb_match;
	wire tb_mismatch = ~tb_match;

	stimulus_gen stim1 (.clk, .a, .b, .sub);
	RefModule good1 (.a, .b, .sub, .sum(sum_ref));
	TopModule top_module1 (.a, .b, .sub, .sum(sum_dut));

	final begin
		if (stats1.errors_sum) $display("Hint: Output '%s' has %0d mismatches. First mismatch occurred at time %0d.", "sum", stats1.errors_sum, stats1.errortime_sum);
		else $display("Hint: Output '%s' has no mismatches.", "sum");
		$display("Hint: Total mismatched samples is %1d out of %1d samples\n", stats1.errors, stats1.clocks);
		$display("Simulation finished at %0d ps", $time);
		$display("Mismatches: %1d in %1d samples", stats1.errors, stats1.clocks);
	end

	assign tb_match = ( { sum_ref } === ( { sum_ref } ^ { sum_dut } ^ { sum_ref } ) );

	always @(posedge clk, negedge clk) begin
		stats1.clocks++;
		if (!tb_match) begin
			if (stats1.errors == 0) stats1.errortime = $time;
			stats1.errors++;
		end
		if (sum_ref !== ( sum_ref ^ sum_dut ^ sum_ref ))
		begin if (stats1.errors_sum == 0) stats1.errortime_sum = $time;
			stats1.errors_sum = stats1.errors_sum+1'b1; end
	end

	initial begin
		#1000000
		$display("TIMEOUT");
		$finish();
	end

endmodule
