module top_module(input clk, input [7:0] d, input [1:0] sel, output [7:0] q);
  wire [7:0] q1, q2, q3;
  my_dff8 ff1 (.clk(clk), .d(d),  .q(q1));
  my_dff8 ff2 (.clk(clk), .d(q1), .q(q2));
  my_dff8 ff3 (.clk(clk), .d(q2), .q(q3));
  reg [7:0] q_int;
  always @(*) begin
    case (sel)
      2'd0: q_int = d;
      2'd1: q_int = q1;
      2'd2: q_int = q2;
      2'd3: q_int = q3;
    endcase
  end
  assign q = q_int;
endmodule
