module add16(input [15:0] a, input [15:0] b, input cin, output [15:0] sum, output cout);
  wire [15:0] carry;
  genvar i;
  for (i=0; i<16; i=i+1) begin : stage
    wire c_in = (i==0) ? cin : carry[i-1];
    wire c_out;
    add1 u_add1 (.a(a[i]), .b(b[i]), .cin(c_in), .sum(sum[i]), .cout(c_out));
    assign carry[i] = c_out;
  end
  assign cout = carry[15];
endmodule
